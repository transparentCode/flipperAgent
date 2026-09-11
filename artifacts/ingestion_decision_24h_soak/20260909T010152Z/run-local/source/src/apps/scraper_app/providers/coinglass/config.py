"""CoinGlass scraper configuration."""

from libs.common.config import ConfigManager

CONFIG_FILE_COINGLASS = "configs/coinglass.yaml"

config_manager = ConfigManager()
config_manager.register_file(CONFIG_FILE_COINGLASS)
