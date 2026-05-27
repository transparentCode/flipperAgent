"""TradingView scraper configuration."""

from libs.common.config import ConfigManager

config_manager = ConfigManager()

# Default TV scraper settings
TV_DEFAULTS = {
    "indices": ["CRYPTOCAP:TOTAL2", "CRYPTOCAP:TOTAL3", "CRYPTOCAP:BTC.D"],
    "timeframe": "1h",
    "staleness_ttl_seconds": 10800,  # 3 hours
    "fetch_delay_seconds": 2,  # delay between sequential fetches
    "cookies_path": "secrets/tv_cookies.json",
}
