import pytest
from unittest.mock import patch, MagicMock

from libs.common.config import ConfigManager
from libs.features.indicators.registry import IndicatorRegistry

# Ensure indicators are registered before testing
import libs.features.indicators.momentum.rsi
import libs.features.indicators.momentum.macd
import libs.features.indicators.trend.ema

@pytest.fixture
def mock_config():
    return {
        "features": {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RSI": {"period": 14},
                            "EMA": {"period": 20}
                        }
                    }
                },
                "BTC/USD": {
                    "timeframes": {
                        "15m": {
                            "RSI": {"period": 21}
                        }
                    }
                }
            }
        }
    }

def get_feature_params_with_mock(mock_config_fixture, asset, timeframe, indicator):
    # Setup mock manager with injected data
    config_mgr = ConfigManager()
    
    # We patch self._state inside ConfigManager for the test, bypassing file reading
    old_state = config_mgr._state
    config_mgr._state = mock_config_fixture
    
    try:
        return config_mgr.get_feature_params(asset, timeframe, indicator)
    finally:
        config_mgr._state = old_state


def test_exact_match(mock_config):
    params = get_feature_params_with_mock(mock_config, "BTC/USD", "15m", "RSI")
    assert params == {"period": 21}

def test_timeframe_fallback(mock_config):
    params = get_feature_params_with_mock(mock_config, "BTC/USD", "1h", "RSI")
    assert params == {"period": 14}

def test_asset_fallback(mock_config):
    params = get_feature_params_with_mock(mock_config, "ETH/USD", "1h", "RSI")
    assert params == {"period": 14}

def test_missing_indicator(mock_config):
    params = get_feature_params_with_mock(mock_config, "BTC/USD", "15m", "MACD")
    assert params == {}

def test_integration_with_registry(mock_config):
    # 1. Exact match test
    params_btc_15m = get_feature_params_with_mock(mock_config, "BTC/USD", "15m", "RSI")
    rsi_1 = IndicatorRegistry.get("RSI")(**params_btc_15m)
    assert rsi_1.period == 21
    
    # 2. Fallback test
    params_eth_1h = get_feature_params_with_mock(mock_config, "ETH/USD", "1h", "RSI")
    rsi_2 = IndicatorRegistry.get("RSI")(**params_eth_1h)
    assert rsi_2.period == 14
    
    # 3. Another default test
    params_ema = get_feature_params_with_mock(mock_config, "LTC/USD", "4h", "EMA")
    ema = IndicatorRegistry.get("EMA")(**params_ema)
    assert ema.period == 20
