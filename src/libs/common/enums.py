"""Shared enumerations for the flipperAgent commons layer."""

from enum import Enum

class SystemComponent(str, Enum):
    """Enumeration of known system components for standardized logging."""
    CORE_INFRASTRUCTURE = "CORE_INFRASTRUCTURE"
    DATA_INGESTION_ENGINE = "DATA_INGESTION_ENGINE"
    STRATEGY_ENGINE = "STRATEGY_ENGINE"
    SIGNAL_GENERATOR = "SIGNAL_GENERATOR"
    TRADE_EXECUTION = "TRADE_EXECUTION"
    MARKET_DATA = "MARKET_DATA"
    SIGNAL_APP = "SIGNAL_APP"
    MODEL_STRATEGY = "MODEL_STRATEGY"
    OPTIMIZATION = "OPTIMIZATION"
    RISK_MANAGER = "RISK_MANAGER"
