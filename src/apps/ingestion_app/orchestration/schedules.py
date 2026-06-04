from libs.common.config import ConfigManager
from arq.cron import cron
from libs.common.scheduling import BaseScheduler
from apps.ingestion_app.constants import EXCHANGE_BINANCE
from .tasks import poll_binance_ohlcv, scheduled_gap_fill, poll_l2_depth

class IngestionScheduler(BaseScheduler):
    def __init__(self, config_manager: ConfigManager | None = None):
        self.config_manager = config_manager or ConfigManager()

    def get_cron_jobs(self) -> list:
        """
        Define cron-like periodic tasks for the arq worker.
        """
        # Load from config using a fallback dictionary if missing
        schedules = self.config_manager.get("ingestion.orchestration.schedules", {})
        
        # Use config values, default to what was hardcoded if config fails
        gap_fill_minutes = set(schedules.get("gap_fill_minutes", [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]))
        gap_fill_timeout = schedules.get("gap_fill_timeout", 300)
        
        ohlcv_minutes = set(schedules.get("ohlcv_minutes", [0, 15, 30, 45]))
        ohlcv_timeout = schedules.get("ohlcv_timeout", 120)

        l2_depth_minutes = set(schedules.get("l2_depth_minutes", [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]))
        l2_depth_timeout = schedules.get("l2_depth_timeout", 60)

        return [
            # Gap Fill Task
            cron(
                scheduled_gap_fill,
                minute=gap_fill_minutes,
                run_at_startup=True,
                unique=True,
                timeout=gap_fill_timeout,
            ),
            # Poll OHLCV
            cron(
                poll_binance_ohlcv,
                minute=ohlcv_minutes,
                run_at_startup=True,
                unique=True,
                timeout=ohlcv_timeout,
            ),
            # Poll L2 Orderbook Depth
            cron(
                poll_l2_depth,
                minute=l2_depth_minutes,
                run_at_startup=True,
                unique=True,
                timeout=l2_depth_timeout,
            ),
        ]
