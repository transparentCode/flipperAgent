"""TradingView scraper configuration."""

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_TRADINGVIEW

config_manager = ConfigManager()
config_manager.register_file(CONFIG_FILE_TRADINGVIEW)
